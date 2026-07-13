import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class NameplateColorsTest(unittest.TestCase):
    def fielder(self, position, sub_positions=None):
        return {"role": "野手", "position": position, "sub_positions": sub_positions or []}

    def pitcher(self, starter="-", reliever="-", closer="-", sub_positions=None):
        return {
            "role": "投手",
            "position": "先発" if starter != "-" else "中継ぎ",
            "starter_aptitude": starter,
            "reliever_aptitude": reliever,
            "closer_aptitude": closer,
            "sub_positions": sub_positions or [],
        }

    def test_fielder_nameplate_colors(self):
        cases = [
            (self.fielder("捕手"), ["catcher"]),
            (self.fielder("一塁手", [{"position": "二塁手", "aptitude": "○"}]), ["infield"]),
            (self.fielder("捕手", [{"position": "二塁手", "aptitude": "○"}]), ["catcher", "infield"]),
            (self.fielder("二塁手", [{"position": "捕手", "aptitude": "○"}]), ["infield", "catcher"]),
            (self.fielder("外野手", [{"position": "三塁手", "aptitude": "○"}]), ["outfield", "infield"]),
            (self.fielder("捕手", [{"position": "二塁手", "aptitude": "◎"}, {"position": "外野手", "aptitude": "○"}]), ["catcher", "infield", "outfield"]),
            (self.fielder("捕手", [{"position": "二塁手", "aptitude": "○"}, {"position": "外野手", "aptitude": "◎"}]), ["catcher", "outfield", "infield"]),
            (self.fielder("捕手", [{"position": "二塁手", "aptitude": "○"}, {"position": "外野手", "aptitude": "○"}]), ["catcher", "infield", "outfield"]),
            (self.fielder("外野手", [{"position": "捕手", "aptitude": "○"}, {"position": "二塁手", "aptitude": "○"}]), ["outfield", "catcher", "infield"]),
            (self.fielder("捕手", [{"position": "一塁手", "aptitude": "△"}, {"position": "二塁手", "aptitude": "◎"}, {"position": "外野手", "aptitude": "○"}]), ["catcher", "infield", "outfield"]),
            (self.fielder("捕手", [{"position": "一塁手", "aptitude": "△"}, {"position": "二塁手", "aptitude": "○"}]), ["catcher", "infield"]),
            (self.fielder("捕手", [{"position": "一塁手", "aptitude": "○"}, {"position": "二塁手", "aptitude": "◎"}, {"position": "三塁手", "aptitude": "△"}]), ["catcher", "infield"]),
        ]
        for player, expected in cases:
            with self.subTest(player=player):
                self.assertEqual(app.get_player_nameplate_colors(player), expected)

    def test_pitcher_nameplate_colors(self):
        cases = [
            (self.pitcher("◎", "-", "-"), ["starter"]),
            (self.pitcher("○", "-", "-"), ["starter"]),
            (self.pitcher("-", "◎", "-"), ["relief"]),
            (self.pitcher("-", "-", "○"), ["relief"]),
            (self.pitcher("◎", "○", "-"), ["starter", "relief"]),
            (self.pitcher("○", "◎", "-"), ["relief", "starter"]),
            (self.pitcher("○", "○", "○"), ["starter", "relief"]),
            (self.pitcher("◎", "-", "◎"), ["starter", "relief"]),
            (self.pitcher("○", "-", "◎"), ["relief", "starter"]),
            (self.pitcher("○", "－", "◎"), ["relief", "starter"]),
        ]
        for player, expected in cases:
            with self.subTest(player=player):
                self.assertEqual(app.get_player_nameplate_colors(player), expected)

    def test_pitcher_with_imported_or_future_fielder_aptitude_colors(self):
        cases = [
            (self.pitcher("◎", "-", "-", [{"position": "外野手", "aptitude": "○"}]), ["starter", "outfield"]),
            (self.pitcher("-", "◎", "-", [{"position": "捕手", "aptitude": "○"}]), ["relief", "catcher"]),
            (self.pitcher("◎", "○", "-", [{"position": "一塁手", "aptitude": "○"}]), ["starter", "relief", "infield"]),
            (self.pitcher("◎", "○", "-", [{"position": "捕手", "aptitude": "○"}, {"position": "一塁手", "aptitude": "◎"}, {"position": "外野手", "aptitude": "◎"}]), ["starter", "relief", "infield"]),
            (self.pitcher("◎", "○", "-", [{"position": "捕手", "aptitude": "◎"}, {"position": "一塁手", "aptitude": "◎"}, {"position": "外野手", "aptitude": "◎"}]), ["starter", "relief", "catcher"]),
            (self.pitcher("◎", "-", "-", [{"position": "捕手", "aptitude": "△"}]), ["starter", "catcher"]),
            (self.pitcher("◎", "○", "-", [{"position": "捕手", "aptitude": "○"}, {"position": "一塁手", "aptitude": "○"}, {"position": "外野手", "aptitude": "○"}]), ["starter", "relief", "catcher"]),
        ]
        for player, expected in cases:
            with self.subTest(player=player):
                self.assertEqual(app.get_player_nameplate_colors(player), expected)
                self.assertLessEqual(len(app.get_player_nameplate_colors(player)), 3)

    def test_nameplate_css_uses_crisp_horizontal_splits(self):
        one = app.nameplate_background_css(["starter"])
        two = app.nameplate_background_css(["starter", "relief"])
        three = app.nameplate_background_css(["starter", "relief", "infield"])
        self.assertIn("linear-gradient(#ff8a7c,#ff6d61)", one)
        self.assertIn("/ 50.0000% 100% no-repeat", two)
        self.assertIn("0.0000% 0% / 50.0000% 100% no-repeat", two)
        self.assertIn("100.0000% 0% / 50.0000% 100% no-repeat", two)
        self.assertIn("/ 33.3333% 100% no-repeat", three)
        self.assertIn("0.0000% 0% / 33.3333% 100% no-repeat", three)
        self.assertIn("50.0000% 0% / 33.3333% 100% no-repeat", three)
        self.assertIn("100.0000% 0% / 33.3333% 100% no-repeat", three)

    def test_empty_and_saved_style_values_fallback_safely(self):
        self.assertEqual(app.get_player_nameplate_colors({"role": "野手", "position": "", "sub_positions": None}), [])
        self.assertEqual(app.nameplate_background_css([]), "")
        saved_pitcher = {"role": "投手", "position": "先発", "starter_aptitude": "", "reliever_aptitude": None, "closer_aptitude": "－", "sub_positions": ""}
        self.assertEqual(app.get_player_nameplate_colors(saved_pitcher), ["starter"])
        self.assertEqual(app.normalize_sub_positions("一塁手○;二塁手◎"), [{"position": "一塁手", "aptitude": "○"}, {"position": "二塁手", "aptitude": "◎"}])

    def test_numeric_aptitude_levels_match_compatibility_mapping(self):
        self.assertEqual([app.normalize_pitcher_aptitude_level(v) for v in [0, 1, 2]], [0, 1, 2])
        self.assertEqual([app.normalize_fielding_aptitude_level(v) for v in [0, 1, 2, 3]], [0, 1, 2, 3])
        self.assertEqual([app.normalize_fielding_aptitude_level(v) for v in ["0", "1", "2", "3"]], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
